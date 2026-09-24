# Protocol traffic verification

Verified locally on 2026-09-20. Phase 6 is implemented across the backend,
frontend, and teaching assets. Public deployment and image pins are unchanged.
Rollback work is excluded at the user's request.

## Implemented behavior

- REST traffic retains its existing response/event shape and capture policy.
- GraphQL capture uses the actual HTTP status and independent execution outcome:
  success, partial error, or error. HTTP 200 alone never means success.
- Four native inventory RPCs expose canonical gRPC status codes in the monitor.
  Authentication failures, cancellation, and expired deadlines are recorded.
  Health and reflection are excluded from operation capture.
- Both new protocols require an explicit valid traffic session header. Events
  use the existing session routing and log access policy. The UI displays the
  session ID for use in GraphiQL and native clients.
- Generated correlation IDs connect live events to saved records. No database
  migration or REST OpenAPI change is needed. New protocol summaries are stored
  inside the existing traffic-log envelope's `responseBody`.
- Capture retains only bounded metadata: allowlisted GraphQL root fields/error
  codes and canonical RPC method/status. Documents, variables, aliases, client
  operation names, query strings, raw errors, message bodies, and credentials
  are omitted independently of existing REST obfuscation settings.
- Capture failures cannot change operation results. Completion/cancellation
  races produce one record. Async GraphQL capture waits for completion.

Use the [protocol testing lab](PROTOCOL_TESTING_LAB.md) and checked-in
[GraphQL examples](../examples/protocols/inventory.graphql).

## Normal verification

- Backend `./mvnw -Pintegration-tests verify`: 509 tests and 41 integration tests
  passed, including PostgreSQL concurrency coverage and PMD.
- Subsequent targeted verification of strengthened protocol tests: 27 passed
  across five classes, including 15 additional cases. All 524 current ordinary
  tests have passing evidence; unchanged tests reuse the full verification run.
- Frontend: 534 Vitest tests passed; production build and ESLint passed.
- Chromium traffic suite: 4 passed, including real GraphQL partial-error
  rendering, existing REST events, WebSocket connection, and clearing events.
- Chromium commerce suite: 5 passed for REST/GraphQL journeys, transport switching,
  token refresh, admin adjustments, and GraphQL execution errors.
- A real unauthenticated grpcurl request appeared in the live browser as
  `gRPC / GetStock / UNAUTHENTICATED (16)` in red, with a correlation ID.
- The lab replayed one +3 adjustment through REST, GraphQL, and native gRPC.
  All returned the same movement ID; stock changed from 5 to 8 once. Direct and
  proxied REST/GraphQL stock reads agreed. Saved protocol records contained
  metadata only.
- Disposable merged Compose configuration passed `config --quiet`. No gateway
  code or normal deployment profiles were modified in this phase.
- Latest pinned `ai-testers-api/l20`: **190 passed, zero skipped, zero failures,
  zero retries/flaky results** with GraphQL and gRPC active. Course sources and
  assertions were unchanged. Both generated REST OpenAPI documents are
  structurally identical to the previous passing gRPC candidate.

## Framework mutation layer

Backend command:

```bash
./mvnw -Pmutation-testing test-compile pitest:mutationCoverage \
  '-DtargetClasses=com.awesome.testing.traffic.protocol.*' \
  '-DtargetTests=com.awesome.testing.traffic.protocol.*Test,com.awesome.testing.grpc.GrpcProtocolTrafficTest'
```

Final PITest result: 59 mutants, **57 killed, 2 timed out, 0 survived,
0 without coverage**. Mutated line coverage is 109/109. Timeouts are reported
separately from assertion kills. Initial gaps in async completion, cancellation,
operation selection, and duration assertions were addressed before this run.

Frontend command: `npx stryker run --mutate src/lib/trafficPresentation.ts`.
Result: **70 killed, 1 survived, 0 timed out, 0 without coverage** (98.59%).
The survivor removes the separator in `codes.join(', ')`; native gRPC events
contain exactly one status code, so this is equivalent under the emitted
protocol contract. No meaningful error-classification survivor remains.

Both components' normal mutation configurations include the new production
classes/helper and targeted tests for subsequent runs.

## Semantic mutation layer

Three requirement-driven candidates were frozen before strengthening tests and
run in disposable copies after framework mutation:

- Store the raw GraphQL document instead of a safe operation summary.
- Store the raw gRPC status description instead of its canonical code.
- Treat HTTP 200 as successful despite GraphQL execution errors.

**3 killed, 0 survived, 0 invalid, 0 equivalent.** All candidates compiled,
passed their unmodified baselines, and failed the frozen mutant tests. These
results are separate from the framework scores above.

## Reproducibility and limitations

Backend candidate: `awesome-backend:protocol-local`, local image ID
`sha256:38e8c8dcd2876d2660b151e78d32bccf60bf26fbd7ef64a1e6ea8b137a48632f`.
It contains the verified Java 25 application JAR over the prior pinned runtime.
The frontend preview mounts the verified production `dist` into the existing
frontend nginx image; it is not a published frontend release.

Working-tree changes were tested over these repository HEADs:

- Stack: `f0c5be16493db0c2b57fe7ed5061a0f801680372`.
- Backend: `b4973a53b1697f84a479b6aceeb870cd48423091`.
- Frontend: `41e177a6e4b4f53ffb75d0e37b0666dcb9508277`.
- Course: `2e8f99e6d5d480f16149d40e51b29da69d4ce550`.

Local evidence lives under `outputs/protocol-candidate-l20/`,
`outputs/protocol-verification/`, and `outputs/protocol-semantic-*.json`.
These ignored artifacts can contain local fixture data and are not release assets.

This is a session-scoped training monitor, not distributed tracing or a new
retention/metrics system. Existing queue/database retention behavior is unchanged.
Legacy public traffic mode remains public. Fragment-only GraphQL root selections
may display only the operation kind. Cancelled clients may not receive correlation
trailers. Public rollout and candidate verification of all historical lessons
remain release work; only the latest unchanged suite was rerun for this phase.
