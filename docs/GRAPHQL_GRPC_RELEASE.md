# GraphQL and gRPC release 3.8.0

Status: release preparation in progress. Public rollout has not yet run.

## Scope

Backend 3.8.0 adds the always-included GraphQL commerce API, authenticated
GraphiQL execution, four optional admin inventory gRPC methods, and safe protocol
traffic capture. Frontend 3.8.0 keeps REST as the default and adds the per-tab
GraphQL transport plus protocol-aware traffic presentation.

Both public sites will use the same immutable application releases. Stable data
remains PostgreSQL-backed; the aitesters sandbox keeps its existing disposable
profile. No schema migration or explicit demo-state reset is needed. Existing production
rate limits are preserved. The sandbox now receives a separate runtime file and
Vault-managed JWT signing key: pre-deployment verification found that the stable
API accepted sandbox tokens. Both cross-site directions are now an explicit
post-deployment rejection gate. Stable signing material is unchanged. Rollback work is excluded as requested.

Native gRPC is enabled explicitly by the server Compose file, with host bindings
limited to `127.0.0.1:9091` (stable) and `127.0.0.1:9092` (sandbox). Reflection is
disabled. Use the documented [SSH tunnel](GRPC_INVENTORY.md#server-deployment-and-ssh-access).
Swagger remains the REST explorer; GraphiQL and the `.proto` contract describe
the additional protocols.

## Source and publication

- Backend: [PR #59](https://github.com/slawekradzyminski/test-secure-backend/pull/59),
  commit `44fea05be0447954b169730cd837c9a05a619331`, tag `v3.8.0`.
- [Backend release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/35515279059)
  owns verification and multi-platform publication with SBOM and provenance.
- Backend image: `slawekradzyminski/backend:3.8.0@sha256:0fb27619c9048b93dcf38bc92c48ede0ff762d4956c009ef62a0f981cd112a9f`.
- Frontend: [PR #67](https://github.com/slawekradzyminski/vite-react-frontend/pull/67),
  commit `fffa956b0e2b940391480982690959c904674c18`, tag `v3.8.0`.
- [Frontend release workflow](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/35516406179).
- Frontend image: `slawekradzyminski/frontend:3.8.0@sha256:302e921c505c6b76a15c25fadcd6fb8ab3ff611c28b74a66c3a471b55ac9f8e5`.
- LocalStack release references and deployment results will be recorded after rollout.

## Compatibility evidence

Course revision: `2e8f99e6d5d480f16149d40e51b29da69d4ce550`.

The frozen historical suites passed **1,320 tests across 19 runnable lessons
(l2–l20), with zero failures, skipped tests, or retries/flaky results** against
the local feature candidate. `l1` is scaffolding without a runnable Playwright
configuration and is not counted as a passing suite. Lesson sources and
assertions were unchanged. Exact-priced disposable catalog fixtures are explained
in [course compatibility](COURSE_COMPATIBILITY.md); this does not change production
money behavior or catalog prices.

Backend source CI passed all four gates: Maven, PostgreSQL integration, local
startup, and Docker startup. Prior feature checks include 524 ordinary backend
tests, 41 integration tests, 534 frontend unit tests, nine traffic/commerce
browser cases, and real native gRPC calls. See
[protocol verification](PROTOCOL_TRAFFIC_VERIFICATION.md) for exact commands and
separate framework/semantic mutation results.

Deployment configuration checks include all four base Compose files and their
gRPC override combinations. The immutable release checker now requires the two
loopback gRPC bindings and disabled reflection. A frozen semantic mutation that
changes the stable binding to `0.0.0.0` compiled as valid Compose and was killed
by this checker. A second candidate redirects the sandbox to the stable runtime
file, removing signing-key isolation; it is also rejected. Final deployment
semantic results: **2 killed, 0 survived, 0 invalid, 0 equivalent**. There is no
configured framework mutation scope for these Python/YAML deployment checks.
An intermediate rebase of the signing-key mutation patch failed to apply; it was
corrected and rerun before the final valid result, and was not counted as a kill.

The same **1,320 unchanged tests passed again against the published backend
3.8.0 digest**, with no skips, failures, or retries. Public smoke-test results
will be recorded after rollout.
Private local evidence is under `outputs/protocol-release/` and
`outputs/protocol-release-all/`; these directories are not release assets.
