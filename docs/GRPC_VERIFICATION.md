# Native inventory gRPC verification

Phase 5 adds a versioned `awesome.inventory.v1.InventoryService` with four unary
RPCs: `GetStock`, `ListInventory`, `AdjustStock`, and `ListStockMovements`.
This is an additional testing API for inventory, not a whole-application protocol
migration or a claimed performance optimization. All methods require an admin
JWT and reuse the existing inventory transactions and audit records.

The `grpc` profile is optional. GraphQL and GraphiQL remain included by default.
The local listener defaults to `127.0.0.1:9091`; the new Compose override publishes
only on loopback and preserves the base active profiles. Reflection is opt-in,
and both reflection and health require admin authentication. No public gRPC
proxy route, deployment image update, database migration, or frontend transport
change was introduced.

## Build and normal verification

The backend uses Spring Boot 4.1.0's managed native gRPC starter, Spring gRPC
1.1.0, gRPC Java 1.80.0, Protobuf 4.34.2, and the Boot-managed Protobuf Maven
plugin. Generated sources are excluded from PMD, JaCoCo, and mutation scope;
handwritten adapters remain checked.

- `./mvnw -Pintegration-tests verify`: **493 normal tests and 41 integration tests
  passed**, including PMD and coverage gates.
- Three later tests for optional reflection, sanitized unexpected failures, and
  an in-flight client deadline passed in targeted runs. Strengthened filter and
  boundary assertions also passed against the original implementation.
- The native tests use real TCP channels and Given/When/Then structure. They
  cover all RPCs; missing, invalid and expired tokens; current roles after
  demotion; per-call identity; admin-only health/reflection; message limits;
  presence and pagination; status mapping; filters; audit identity; scoped UUIDs;
  replay/payload mismatch; stock overflow; and REST/GraphQL consistency.
- The deadline test blocks an adjustment after dispatch, observes the caller's
  `DEADLINE_EXCEEDED`, releases the operation, and retries the identical request.
  Stock changes once and movement history contains one adjustment. This backs
  the documented warning that an expired deadline does not guarantee rollback.
- Two PostgreSQL native-RPC concurrency tests pass: concurrent identical requests
  commit one movement, and competing deductions cannot make stock negative.
- Default-profile availability tests confirm that the gRPC lifecycle is absent
  while GraphQL, REST, and Swagger remain available.

## Candidate and whole-stack checks

Local image: `awesome-backend:grpc-local`, ID
`sha256:1a3b7f493834a0adeae63aa00ef2df13814171c96a7f4b9edb0d312d2ab59f6a`.
It contains the verified application JAR over the previously pinned runtime
image. It has not been published or deployed.

`docker-compose.grpc.yml` validates when merged with lightweight, full, server,
and compatibility configurations. The compatibility runner's new `--grpc-preview`
flag opts the ordinary backend into gRPC and checks its loopback listener before
running the unchanged REST suite.

- Frozen course revision: `2e8f99e6d5d480f16149d40e51b29da69d4ce550`.
- Latest lesson: **190/190 passed**, no skips, failures, or retries, with gRPC active.
- Course TypeScript source digests are preserved. Both OpenAPI snapshots are
  structurally identical to the previous candidate's baseline.
- Direct and nginx-proxied GraphQL requests still pass, including anonymous 401.
- Independent grpcurl smoke checks exercise all four RPCs against the Docker
  listener on `127.0.0.1:14991`, using the checked-in schema with reflection off.
  They verify admin access, rejection of anonymous/invalid/customer credentials,
  single-application replay, mismatch status, and stock consistency in both
  directions with REST/GraphQL. HTTP reads were checked directly and through nginx.
- The disposable stack was removed after verification. Existing user containers,
  unrelated working-tree edits, and normal deployment image pins were preserved.

Course evidence: `outputs/grpc-candidate-l20/summary.json` and its OpenAPI snapshots.
Native evidence: `outputs/grpc-verification/native-summary.json`. These local
ignored artifacts are private; this document is the sanitized report.

## Layer 1: framework mutation

Command:

```bash
./mvnw -Pmutation-testing \
  -DtargetClasses='com.awesome.testing.grpc.InventoryGrpc*' \
  -DtargetTests='com.awesome.testing.grpc.InventoryGrpc*Test' \
  test-compile pitest:mutationCoverage
```

The initial run found two meaningful filter survivors: dropping search or
category restrictions was not detected by a one-product fixture. The fixture
now includes independently nonmatching products, and both mutants are killed.
The final run produced **53 mutants: 42 killed, 7 timed out, 4 survived, 0 no
coverage**. PITest counts killed/timeouts together as 49 detected (92%). The seven
timeouts remove RPC dispatch, completion, error signaling, or call closure, so
calls no longer receive their expected terminal response.

The four survivors replace the listener return value with null after the call
has already been closed for invalid credentials or insufficient permissions.
The terminal wire status remains unchanged. These are inconsequential to the
observable RPC contract; they are reported as survivors, not counted as kills.
No meaningful authorization, state, filtering, or data-flow survivor remains.
The report covers the new gRPC adapters only; passing evidence for unchanged
existing PITest targets is retained from earlier increments.

Evidence: `outputs/grpc-verification/pit-final.xml` and `pit-final.log`.

## Layer 2: semantic mutation

Two requirement-driven candidates were frozen before the native contract tests
were introduced, then run with the shared lab after framework mutation. Baseline
and mutant compilation succeeded in disposable copies; both baselines passed.

| Candidate | Violated requirement | Result |
| --- | --- | --- |
| `backend-grpc-loses-admin-policy` | Customers must not access inventory RPCs | Killed by expected `PERMISSION_DENIED` assertions |
| `backend-grpc-discards-request-id` | Replaying the same product/request ID must not apply stock twice | Killed by replay/movement assertions |

Semantic totals: **2 killed, 0 survived, 0 invalid, 0 equivalent**, separate from
framework results. Evidence: `outputs/grpc-verification/semantic-mutations.json`.
The later deadline test strengthens this unchanged implementation; the frozen
semantic candidates and their passing/killed evidence remain applicable.

## Release and lightweight training toggle

The protocol-aware traffic presentation, [teaching lab](PROTOCOL_TESTING_LAB.md),
and public rollout are complete; see the [release record](GRAPHQL_GRPC_RELEASE.md).
The [classroom runbook](GRPC_TRAINING_RUNBOOK.md) uses the pinned 3.8.0 image
through the lightweight gRPC Compose override. The standalone override and its
lightweight, full, and server combinations pass `docker compose config --quiet`.
The release-image checker confirms the lightweight and full overrides keep the
reviewed backend image, enable `graphql,grpc`, disable reflection, and publish
only on host loopback. There is no framework mutation scope for this YAML/Python
deployment change. The frozen semantic candidate
`stack-lightweight-grpc-publishes-on-all-interfaces` compiled as valid Compose
but was killed by the checker: **1 killed, 0 survived, 0 invalid, 0 equivalent**.
